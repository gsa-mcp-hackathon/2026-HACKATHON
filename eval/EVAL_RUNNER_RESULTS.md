<!-- Paste-ready section for the Evaluation Documentation deliverable.
     Regenerate with:  PYTHONPATH=src python eval/eval_runner.py --live
     The script writes a fresh copy to eval/results/eval_runner_<UTC>/summary.md -->

## Testing methodology

`eval/eval_runner.py` drives the real registered MCP tools through an
in-process FastMCP client, the same protocol path a production agent uses.
OpenFEMA is replaced by a synthetic, OpenFEMA-shaped fixture (36 rows: 35 Florida,
1 Louisiana; no real or personal data) whose expected answers are known in advance. A small OData
evaluator applies each tool's real `$filter` string to the fixture, so the
harness also checks that the tools build correct upstream queries.
Correctness is checked against an **independent oracle** written separately
with exact rational arithmetic (`fractions.Fraction`) and `math.fsum`, so a
floating-point or logic error in the server cannot also appear in the
expected answers. An optional `--live` pass then calls the public OpenFEMA API
(read-only) to measure end-to-end latency and confirm provenance stamps.

The script exits non-zero on any failure, so it also works as a CI gate.

## Automated evaluation results

Generated 2026-10-30T12:05:32Z by `eval/eval_runner.py` in 3.1 s (Python
3.12.3, FastMCP 4.0.11, commit `d792ad0-dirty`).

**Overall: 69/69 cases passed (100.0%).**

| Suite | Cases | Passed | Pass rate | What it proves |
| --- | --- | --- | --- | --- |
| happy_path | 5 | 5 | 100% | Well-formed envelope from every tool |
| correctness | 4 | 4 | 100% | Equals independent Fraction/fsum oracle |
| boundary | 13 | 13 | 100% | Threshold edges and pagination edges |
| malformed_input | 22 | 22 | 100% | Rejected pre-I/O with invalid_arguments |
| reliability | 8 | 8 | 100% | Outage, empty data, idempotency, concurrency |
| security | 11 | 11 | 100% | Injection, sanitization, leaks, rate limit, read-only |
| latency | 6 | 6 | 100% | Repeated calls complete without error |

### Governance and security metrics

| Metric | Result |
| --- | --- |
| Successful responses carrying full provenance (_provenance) | 202/202 |
| Successful responses carrying the review caveat | 202/202 |
| Error responses in structured envelope (error, error_code, hint, retryable) | 30/30 |
| Responses leaking tracebacks / paths / raw pydantic dumps | 0/232 |
| Upstream calls made for rejected (invalid) inputs | 0 across 24 rejected calls |

### In-process latency (server overhead, fixture upstream)

| Tool | Calls | Errors | p50 ms | p95 ms | max ms |
| --- | --- | --- | --- | --- | --- |
| build_oversight_triage_queue | 25 | 0 | 1.69 | 2.0 | 2.24 |
| get_cost_share_anomalies | 25 | 0 | 1.33 | 1.54 | 1.59 |
| find_repeated_worksheets | 25 | 0 | 1.26 | 1.6 | 1.71 |
| detect_category_outliers | 25 | 0 | 1.36 | 1.71 | 1.93 |
| generate_evidence_brief | 25 | 0 | 1.2 | 1.38 | 1.43 |
| explain_risk_indicator | 25 | 0 | 1.14 | 1.44 | 2.0 |

Network time to OpenFEMA is excluded here by design; see the live table.

### Live OpenFEMA smoke test (read-only, Vermont)

Cold = first call in this process (may still be served by OpenFEMA's CDN);
warm = repeat call answered by the server's 300 s response cache. "Retrieved
at" is OpenFEMA's own response rundate. "Records read" of 10000 means the
per-call cap was hit and the tool reported `data_scope.possibly_truncated=true`.

| Tool | OK | Items | Records read | Cold ms | Warm ms | Dataset last updated | Retrieved at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| build_oversight_triage_queue | yes | 1257 | 10000 | 928 | 42 | 2026-10-29T15:10:36.709Z | 2026-10-30T12:04:20.694Z |
| get_cost_share_anomalies | yes | 1348 | 1349 | 357 | 11 | 2026-10-29T15:10:36.709Z | 2026-10-30T12:04:23.304Z |
| find_repeated_worksheets | yes | 0 | 10000 | 408 | 11 | 2026-10-29T15:10:36.709Z | 2026-10-30T12:04:24.304Z |
| detect_category_outliers | yes | 69 | 6638 | 370 | 10 | 2026-10-29T15:10:36.709Z | 2026-10-30T12:04:26.221Z |
| generate_evidence_brief | yes | 1 | n/a | 339 | n/a | 2026-10-29T15:10:36.709Z | 2026-10-30T12:04:27.398Z |

Interpretation note: 1,348 of 1,349 Vermont projects at or above $100K fall
outside the default 0.70-0.95 band because 1,323 of them have a federal-share
ratio of exactly 1.00 (checked by a direct OpenFEMA query). These are
authorized 100% shares, not anomalies. Use `band_high=1.0` for such
jurisdictions, which the tool's `policy_context` field already advises.

## Defects found by this harness (and fixed)

| # | Defect | Impact | Fix | Regression guard |
| --- | --- | --- | --- | --- |
| 1 | Rate limiter never fired: FastMCP issues a new session id on every call, so each call got an empty per-session bucket | The 60 calls/min guardrail was not being enforced | Added a process-wide ceiling (`rate_limit_global_calls_per_minute`, default 600) checked alongside the per-session bucket | `tests/test_server.py::test_global_rate_limit_holds_when_session_ids_rotate` and the security suite |
| 2 | Schema-level argument errors were labeled `tool_execution_failed`, `retryable=true`, with raw pydantic text including a documentation URL | The agent was told to retry a call that can never succeed | Middleware walks the exception cause chain and returns `invalid_arguments`, `retryable=false`, with one compact hint per field | malformed_input suite (22 cases) |
| 3 | Unknown internal exceptions echoed their message to the model | Possible leak of paths or internals | Generic `internal_error` message; traceback goes to the server log only | security suite "internal error does not leak internals" |
| 4 | Three tools (`build_oversight_triage_queue`, `generate_evidence_brief`, `explain_risk_indicator`) published parameters with no description, bounds or enum; triage `pagination` was untyped | The LLM had to guess formats and limits | Shared annotated parameter types in `models.py` used directly in tool signatures | `tests/test_server.py::test_every_tool_parameter_is_described_for_the_llm` |

## Case inventory

| Suite | Case | Tool | Result |
| --- | --- | --- | --- |
| happy_path | cost-share envelope | get_cost_share_anomalies | pass |
| correctness | cost-share flags == Fraction oracle | get_cost_share_anomalies | pass |
| correctness | category-C outliers == oracle | detect_category_outliers | pass |
| correctness | repeated groups == oracle (no cross-disaster merge) | find_repeated_worksheets | pass |
| correctness | triage queue == oracle and ranked by convergence | build_oversight_triage_queue | pass |
| happy_path | evidence brief for a triage item | generate_evidence_brief | pass |
| happy_path | methodology card (x3 indicators) | explain_risk_indicator | pass |
| boundary | ratio == band_low (0.70) is NOT flagged | get_cost_share_anomalies | pass |
| boundary | ratio 0.6999 is flagged | get_cost_share_anomalies | pass |
| boundary | ratio == band_high (0.95) is NOT flagged | get_cost_share_anomalies | pass |
| boundary | ratio 0.9501 is flagged | get_cost_share_anomalies | pass |
| boundary | band_high=1.0 accepts authorized 100% share | get_cost_share_anomalies | pass |
| boundary | below min_total_obligated is ignored | get_cost_share_anomalies | pass |
| boundary | non-finite 'NaN' total is ignored | get_cost_share_anomalies | pass |
| boundary | other-state rows never leak into FL | get_cost_share_anomalies | pass |
| boundary | first page limit=2 -> has_more, next_offset=2 | get_cost_share_anomalies | pass |
| boundary | last partial page | get_cost_share_anomalies | pass |
| boundary | offset past end -> empty page, no error | get_cost_share_anomalies | pass |
| boundary | limit=100 (documented maximum) accepted | get_cost_share_anomalies | pass |
| boundary | min_repeat_count=4 drops the 3-PW group | find_repeated_worksheets | pass |
| malformed_input | 22 cases: state name, 3-letter/digit/empty/missing/wrong-type state, inverted band, band > 1, negative minimum, sigma < 1 and > 10, repeat count 1, category Z and "CC", unknown indicator, PW 0, negative disaster, page limit 101 and 0, negative offset, unknown argument, unknown pagination field | all six tools | 22/22 pass, 0 upstream calls |
| reliability | OpenFEMA outage -> upstream_unavailable | build_oversight_triage_queue | pass |
| reliability | no rows for state -> total 0, not an error | get_cost_share_anomalies | pass |
| reliability | no baseline -> refine_request with hint | detect_category_outliers | pass |
| reliability | PW not found -> refine_request | generate_evidence_brief | pass |
| reliability | ambiguous PW -> asks for disambiguation | generate_evidence_brief | pass |
| reliability | disambiguated PW -> one record | generate_evidence_brief | pass |
| reliability | idempotent: repeat call returns same queue | build_oversight_triage_queue | pass |
| reliability | 20 concurrent calls: all succeed, identical output | build_oversight_triage_queue | pass |
| security | quote injection in state_code | build_oversight_triage_queue | pass |
| security | OData operator injection in applicant_id | generate_evidence_brief | pass |
| security | prompt-injection text sanitized + truncated | build_oversight_triage_queue | pass |
| security | internal error does not leak internals | get_cost_share_anomalies | pass |
| security | read-only annotation + documented params (x6 tools) | all six tools | pass |
| security | 6th call in a minute -> rate_limit_exceeded | explain_risk_indicator | pass |
| latency | 25 sequential calls, 0 errors (x6 tools) | all six tools | pass |

## Limitations of this evaluation

* The fixture is synthetic. It proves rule correctness and guardrails, not
  that the indicators are useful on real portfolios; for that, see the live
  differential evaluation in `eval/run_hackathon.py` and the agent-level
  golden-set evaluation in `eval/evaluation_documentation.md`.
* In-process latency excludes network time and the LLM. Live timings come
  from one state on one day and from a single client.
* The rate-limit test exercises the process-wide ceiling. With multiple app
  replicas, each replica enforces its own ceiling.
