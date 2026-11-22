# lancelot-client

A Databricks App (Streamlit) that acts as an MCP **client** for the `mcp-lancelot-beta` MCP server
(`https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com/mcp`). It is separate from the server: it never
changes the server app or its source folder.

## Pages

* **Test suite**: one button runs the fixed suite C1-C3, V4-V12, V14, T1 (brief section 7) sequentially and shows a
  pass/fail report. Takes up to about 10 minutes; keep the tab open.
* **Try It - FEMA**: one `generate_choropleth` call without running the suite. Pick a preset disaster (each one
  exercises a different map case: many outliers, Puerto Rico, Connecticut's old counties, Alaska code changes) or
  type a number; optional `pw_number`, `applicant_id`, `sigma_threshold`, `as_of`; numbers can be sent as strings,
  and the raw arguments JSON can be edited to test invalid input. The returned HTML is shown inline (adjustable
  height, downloadable), with the plain-language summary, `structuredContent`, recorded checks and a feedback form.
  The last 10 tries stay selectable in the session. Each try is saved as a `try-fema` run with `TRY.widget.html`.
* **Try It - Mermaid**: pick a sample, paste text, or upload a file; optional `diagramType` and `hint`; calls `generate_diagram`
  and shows the PNG and metadata.
* **Connection**: active auth mode, `/health` and `/api/selftest-obo-scope` with the active token, library versions.

## Data rule

The server runs at `APP_TRACE_LEVEL=debug` and keeps copies of documents. **Only synthetic or public documents may be
sent.** `samples/` holds the server's Pokemon samples (`sample.pdf`, `sample.docx`, `sample.xlsx`, `sample.json`,
copied from `lancelot-beta/selftest/`) plus small synthetic text files.

## Auth modes

* **Mode A, signed-in user (preferred).** User authorization with the `apps` scope. The app reads
  `x-forwarded-access-token` from `st.context.headers` and sends it as `Authorization: Bearer ...`. It is verified with
  `GET /health`; if the server answers anything other than 200 (for example 302/401/403), that is recorded as a finding
  and the app switches to Mode B.
* **Mode B, the app's service principal (fallback).** OAuth M2M token from `databricks-sdk` (`WorkspaceClient()`).
  The service principal `app-2vrjmx lancelot-client` (application ID `433aae0e-6618-4cc8-8e6d-2f789c30363d`) needs
  **CAN_USE** on `mcp-lancelot-beta`, granted from the server project. In Mode B, V12 runs as the service principal; the report
  labels it.

The sidebar switch **Force Mode B (service principal)** skips Mode A for the browser session, to exercise the
service-principal path on purpose (recorded as `authFinding.forcedModeB`).

The UI and every report show the active mode. Tokens are never logged, stored, or displayed.

## Where results go

Every suite run and every try-it call writes to
`/Volumes/users/tom_jacobson/lancelot_traces/client-runs/<YYYY-MM-DD>/<clientRunId>/`
(`clientRunId = client-<UTC yyyymmddThhmmssZ>-<6 hex>`):

* `result.json`: per case: id, inputs (file name, bytes, sha256; never document text), auth mode, start/end, client ms,
  HTTP status, MCP isError, errorCode/stage, server `runId`, diagramType, PNG width/height/bytes, expected vs actual,
  verdict, and the server trace check (`runs/<date>/<runId>/trace.json` found, `run.outcome`, match).
* `report.html`: self-contained (inline CSS, PNGs as data URIs, no JavaScript, no links, all text escaped).
* `<case>.png`: each returned diagram.

After each suite run, `client-runs/latest/summary.json` and `client-runs/latest/report.html` are overwritten.
The client never writes under `runs/` or `latest/` (server-owned). Writes use the app's service principal through the
app resource `trace-volume` (WRITE_VOLUME on `users.tom_jacobson.lancelot_traces`). A storage failure is shown and
recorded but never changes a test result.

**Retention: 30 days, automated.** The server project's job "mcp-lancelot-beta trace cleanup" (job ID
637032316790620, daily 03:00 UTC, runs as tom.jacobson@hq.dhs.gov) runs `lancelot-beta/ops/trace_cleanup.py`, which
now cleans both `runs/` and `client-runs/`: it deletes `client-runs/<YYYY-MM-DD>/` folders older than 30 days and never
touches `client-runs/latest/`. The client does not have its own cleanup job (it would duplicate this one).

## Verdicts

`PASS`, `FAIL`, `INFO`, `SKIP`. C2 (user-token forwarding probe) and V11 (read the caller's own folder through this
client) were removed on 2026-11-12: a user's token must never reach the server through another app (DECISIONS D21).
V12 still checks that another user's folder is `ACCESS_DENIED`.

## Layout

* `app.py`: Streamlit pages
* `client/config.py`: deployment settings (server URL, volume, owner email, V12 paths), set in `app.yaml`
* `client/mcp_client.py`: auth modes, plain HTTP probes, MCP sessions (fresh session per call, 130 s timeouts)
* `client/suite.py`: the cases and pure evaluators
* `client/runner.py`: binds auth + storage, incremental writes
* `client/report.py`: `result.json` and `report.html`
* `client/storage.py`: volume paths and writes (client-runs/ only)
* `tests/`: unit tests, no network. `test_network_runner.py` runs the real MCP client code against an in-process
  MCP server; `test_app_smoke.py` drives `app.py` with Streamlit's AppTest (skipped if streamlit is missing).
* `requirements.in`: direct dependencies; `requirements.txt`: the full pinned closure the build installs

## Recorded data

* **Timings** (`result.json` `timingNotes`): `clientMs` is the whole case, including the new MCP session and
  `initialize`; `callMs` is the `tools/call` request alone. The 75 s budget is checked against `clientMs`.
* **Server error messages** are stored verbatim (max 300 characters) only for `INVALID_INPUT`, `UNSUPPORTED_FILE`
  and `ACCESS_DENIED`, whose messages describe the request. For other codes only `messageInfo` (length, SHA-256)
  is kept, so a server message that quotes document text never reaches storage.
* **Versions**: every run records the main package versions, `requirementsSha256` and `pinsMatchInstalled`.
* If the final `result.json` write fails twice, `result.write-error.json` in the run folder names the errors.

## Limits

Uploads over 14 MB are rejected before upload (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE`); pasted text is capped at
4,000,000 characters. The auth decision is reused for 5 minutes between page clicks and always re-checked when a
suite or try-it run starts (or with "Re-check auth now" on the Connection page).

## Tests

```
cd /Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-client
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .
```

## Dependencies

Builds install `requirements.txt`, which pins every package (55) to an exact version, so each deploy installs the same
set. To change a dependency, edit `requirements.in`, then re-resolve for the Apps runtime (Python 3.11, Linux x86_64)
and replace `requirements.txt` with the result, for example:

```
pip install --dry-run --ignore-installed --only-binary=:all: --python-version 3.11 --implementation cp \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --target /tmp/r --report /tmp/r.json \
  -r requirements.in
```

then check it with `pip-audit -r requirements.txt --no-deps --disable-pip`. After a deploy, the next run's
`versions.pinsMatchInstalled` should be `true`.

## Deploy

Only after `databricks apps get lancelot-client --output JSON` shows `RUNNING` with no pending deployment.
When updating app settings through the API, send `description`, `user_api_scopes`, and the full `resources` list
together (omitted fields are reset). See `DECISIONS.md` for choices not covered by the brief.
