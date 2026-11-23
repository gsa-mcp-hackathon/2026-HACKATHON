# V19: Trace-write failure test (manual, on request only)

App: `mcp-lancelot-beta` · Plan reference: `BUILD_PLAN.md` §8a (write strategy), §10 (V19), §11 (D17)

## Run policy

**V19 never runs automatically.** It is not part of the startup self-test, it is not triggered by any deploy, and none of its settings may ever be put in `app.yaml` or committed. It runs only when the user explicitly asks for it (for example, "run V19"). The coding agent must not start it on its own initiative, not even after code changes to `lib/tracer.mjs`; it may only suggest running it.

## What it proves

The tracer writes every run to the Unity Catalog volume `users.tom_jacobson.lancelot_traces` over the Files API. Those writes can fail for reasons outside the app's control (volume permissions changed or revoked, volume renamed, wrong `TRACE_VOLUME`, Files API outage). The design promises that when they do:

1. The real work still completes: the startup self-test now, the `generate_diagram` result in Phase 2. A tracing problem never turns a good result into an error.
2. The failure is visible: each failed write is logged to stdout as `[tracer] <runId> write failed: <path>: <reason>` and, when `trace.json` itself can still be written, listed in `trace.json` under `tracer.writeErrors`.
3. The server does not crash: no failed write becomes an unhandled promise rejection (guide lesson 5.3).

The normal startup self-test only exercises the success path (every write succeeds), so it cannot prove this. V19 deliberately breaks trace writing.

## Why it is manual only

* It deliberately misconfigures the live app. For a few minutes the deployed app runs with broken tracing and, in Part A, cannot write any trace at all.
* It needs two extra deployments (the test deploy, then the restore deploy). Each restart spends LLM tokens on the startup self-test, and any real request during the test would have no trace.
* Part A can only be confirmed by a person, because the agent has no access to app logs in this workspace (`apps logs` / `getAppsLogs` fail with an OAuth token-exchange error) and cannot call the app URL.
* Its result only changes when the tracer's write path changes, so re-running it on every deploy adds risk without adding information.

## Safeguards built into the code

Fault injection (Part C) is controlled by two environment variables read once at process start (`lib/tracer.mjs`, `faultInjectionConfig`):

| Variable | Meaning |
|---|---|
| `TRACE_FAULT_INJECT` | Comma-separated path substrings. Any trace write whose volume path contains one of them fails on purpose, before any network call |
| `TRACE_FAULT_INJECT_UNTIL` | Required ISO-8601 timestamp. Must be in the future and no more than 2 hours after process start. Injection switches itself off when it passes |

* If `TRACE_FAULT_INJECT` is set without a valid `TRACE_FAULT_INJECT_UNTIL` (missing, unparseable, in the past, or more than 2 hours ahead), injection stays off, a warning is logged, and the reason is recorded in `trace.json` (`config.faultInjection.ignoredReason`).
* Unset (the normal state) is completely inert.
* While active, the state is visible in three places: a `[tracer] V19 FAULT INJECTION ACTIVE until ...` warning at startup, `faultInjection` in the `/health` response, and a "V19 fault injection" row in the startup report summary.
* Injected failures are marked `"injected": true` in `tracer.writeErrors`, so they can never be mistaken for a real outage.
* Settings are passed only as a one-off deployment override (below). The next normal deployment uses `app.yaml` again, which contains none of them, so the app returns to normal even if a restore step is forgotten.

## Prerequisites

* The user has asked for V19 in this session and authorized deploying a deliberately broken configuration to the live app.
* The app is `RUNNING` with no pending deployment (`databricks apps get mcp-lancelot-beta --output JSON`).
* The code to test is committed. Note the current commit and the source hash (computed with `computeSourceHash()` from `lib/tracer.mjs`).
* For Part A, the user is available to watch the app's Logs tab and open `/health` during the test window (about 5 minutes).

## Part C: partial write failure (agent-verifiable)

Goal: some trace writes fail, `trace.json` still lands and records them, the self-test result is unaffected.

1. Choose `TRACE_FAULT_INJECT_UNTIL` = now + 30 minutes (UTC, ISO-8601).
2. Deploy with a one-off environment override. The override replaces the `app.yaml` environment for this deployment, so all variables must be listed:

   ```json
   POST /api/2.0/apps/mcp-lancelot-beta/deployments
   {
     "source_code_path": "/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta",
     "mode": "SNAPSHOT",
     "env_vars": [
       { "name": "LLM_ENDPOINT_PRIMARY", "value_from": "llm-primary" },
       { "name": "LLM_ENDPOINT_FALLBACK", "value_from": "llm-fallback" },
       { "name": "TRACE_VOLUME", "value_from": "trace-volume" },
       { "name": "APP_TRACE_LEVEL", "value": "debug" },
       { "name": "STARTUP_SELFTEST", "value": "full" },
       { "name": "TRACE_FAULT_INJECT", "value": "artifacts/gallery/,report.html" },
       { "name": "TRACE_FAULT_INJECT_UNTIL", "value": "<now + 30 min, ISO-8601 UTC>" }
     ]
   }
   ```

   If the API rejects `env_vars` on a deployment, fall back to a temporary, uncommitted edit of `app.yaml` with the same two extra variables, deploy, and revert the file immediately after the deployment starts.
3. Wait for the deployment to reach `SUCCEEDED`, then for a new `runs/<date>/startup-*` folder whose `started.json` `sourceHash` matches (the injected tokens do not block `latest/startup-summary.json`).
4. Check, from `trace.json` and the volume:
   * `config.faultInjection.active` is `true` with the expected tokens.
   * `tracer.writeErrors` lists exactly the gallery PNGs (`artifacts/gallery/*.png`), `report.html`, and `latest/startup-report.html`, every entry with `"injected": true`.
   * Those files are absent from the run folder; everything else is present (`started.json`, `trace.json`, `artifacts/sample.pdf/output.png`, `artifacts/llm/*.json`, `latest/startup-summary.json`).
   * `run.outcome` equals what a normal run gives (`OK`; gallery results are still recorded in `trace.json`).
   * `apps get` shows the app `RUNNING`, not `CRASHED`, at least 2 minutes after the self-test finished.

## Part A: total write failure (user-verified)

Goal: no trace writes are possible at all; the server still completes the self-test and keeps running.

1. Deploy with the same override as Part C, but with `TRACE_VOLUME` set to a volume that does not exist and without the two `TRACE_FAULT_INJECT*` variables:

   ```json
   { "name": "TRACE_VOLUME", "value": "users.tom_jacobson.lancelot_traces_v19_missing" }
   ```

2. The user, during the test window:
   * App Logs tab: confirm lines like `[tracer] startup-... write failed: /Volumes/users/tom_jacobson/lancelot_traces_v19_missing/...` and a final `[selftest] startup-... finished: outcome=FAILED failed=[volume] traceWritten=false`. Note any `unhandled promise rejection` or `uncaught exception` lines (there should be none).
   * Open `https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com/health` (sign in first): confirm `traceVolumeEnv` shows the missing volume, `selftest.state` is `done`, and `selftest.outcome` is `FAILED`.
3. The agent: confirm with `apps get` that the app stays `RUNNING` at least 2 minutes after the self-test window, and that no new run folder appeared in the real volume.

Expected: the `volume` stage fails (by design, the self-test reports the broken volume); pings, extraction, the `sample.pdf` run, and the gallery still execute; the process survives.

## Restore (always, even if a part fails)

1. Deploy normally, with no `env_vars` override, so `app.yaml` applies again.
2. Confirm a new `startup-*` trace appears in the real volume with the expected `sourceHash`, `config.faultInjection.tokens` empty, and `outcome: OK`.
3. If a temporary `app.yaml` edit was used, confirm `git status` shows no change to `app.yaml`.

## Pass / fail

| Part | Pass when |
|---|---|
| C | All Part C checks hold |
| A | Logs show the `[tracer] ... write failed` lines and the `finished` line; `/health` shows the self-test finished; no crash or unhandled-rejection lines; app stays `RUNNING` |
| Restore | Normal startup trace with `outcome: OK` and no fault injection |

Any crash (`app_status` `CRASHED`), any unhandled rejection, a missing `trace.json` in Part C, or a self-test that never finishes in Part A is a failure: fix `lib/tracer.mjs` and re-run V19 only when the user asks.

## Recording results

Add one line per run to `BUILD_PLAN.md` §10 under V19: date, commit, the test and restore deployment IDs, the Part C run ID, the user's Part A observations, and pass/fail per part.
