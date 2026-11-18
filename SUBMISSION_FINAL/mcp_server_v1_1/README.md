# FEMA Evidence & Oversight Graph: MCP server v1.1 (candidate)

Read-only MCP server that helps AI agents prioritize FEMA Public Assistance (PA) Project Worksheets for human review. Each result includes its evidence: the source records, the exact rule and parameters, the record count and cap, the limitations, and a retrieval timestamp. The tools compute the numbers, and an analyst makes the decision.

Status: v1.1 candidate built on November 18, 2026. It combines the tested v1.0 release (recorded run `20261102T152007Z`, which is the code the live Databricks App runs) with the best ideas from the October 30 repository line (a separate data client, a methodology module, a cross-indicator queue, and structured errors). The deployed app and the v1.0 recorded run are unchanged. This tree has its own tests and its own recorded evaluation (see `eval/results/`).

## Layout

```
src/fema_oversight/
  schemas/inputs.py    Pydantic request models, one per tool (validated, described, extra fields forbidden)
  schemas/outputs.py   Pydantic result models (published as each tool's outputSchema)
  data_access.py       PAQuery (what to fetch), OpenFEMASource (hardened HTTP), SnapshotSource (archived data)
  indicators.py        The three review rules as pure functions (no I/O, no MCP)
  methodology.py       Methodology cards, caveat, dataset limitations, provenance builder
  errors.py            ReviewToolError with stable codes: [CODE] message. Hint: ... Retryable: yes|no
  tools/screening.py   screen_category_cost_outliers, find_repeated_worksheet_groups, screen_cost_share_ratios
  tools/review.py      build_review_queue, explain_review_indicator, prepare_evidence_brief
  tools/_registration.py  Read-only annotations and error conversion shared by all tools
  server.py            build_server(source): the only place components are wired; resources, prompt, transport
tests/                 63 unit, contract, tool, and error-handling tests (no network)
eval/run_evaluation.py Evaluation harness (controls, errors, contract, stability, optional live)
```

Dependencies only go one way: `tools` -> `indicators`, `data_access`, `methodology`, `schemas`. `indicators` has no dependencies on MCP or HTTP, so you can read and test each rule without them.

## Tools (built around analyst goals)

| Tool | Analyst goal | Required inputs |
| --- | --- | --- |
| `build_review_queue` | "Where should I start in this disaster?" Runs all three screens, merges them by worksheet, and ranks by number of indicators | `state_code`, `disaster_number` |
| `screen_category_cost_outliers` | "Which projects cost far more than similar work?" | `damage_category_code` plus state and/or disaster |
| `find_repeated_worksheet_groups` | "Is the same project listed more than once?" Closest matches come first | state and/or disaster |
| `screen_cost_share_ratios` | "Which federal-share percentages fall outside the expected band?" | `state_code` |
| `explain_review_indicator` | "How was this produced, and what can't it tell me?" | `indicator` |
| `prepare_evidence_brief` | "Give me the evidence package for this worksheet." Re-runs the indicator for that worksheet | `pw_number`, `disaster_number`, `indicator` |

Every tool has `readOnlyHint: true`, `destructiveHint: false`, and `idempotentHint: true`. Every description includes USE WHEN and DO NOT USE guidance. Resources: `fema-pa://provenance` and `fema-pa://methodology`. Prompt: `disaster_review(state_code, disaster_number)`.

Renamed from v1.0: `detect_category_outliers` -> `screen_category_cost_outliers`, `find_repeated_worksheets` -> `find_repeated_worksheet_groups`, `get_cost_share_anomalies` -> `screen_cost_share_ratios`, `explain_risk_indicator` -> `explain_review_indicator`, `generate_evidence_brief` -> `prepare_evidence_brief`. New in v1.1: `build_review_queue`.

## Run

```
pip install -e ".[dev]"
pytest                      # 63 tests, no network
ruff check . && ruff format --check .
fema-oversight-mcp          # stdio; set DATABRICKS_APP_PORT or PORT for HTTP
python eval/run_evaluation.py --recorded-run-zip FEMA_Hackathon_Submission_2026-11-02.zip --live
```

The recorded-run zip is at `/Volumes/users/phebe_arouni/hackathon_submissions/20261102/FEMA_Hackathon_Submission_2026-11-02.zip`. The harness reads the archived OpenFEMA snapshots and the v1.0 tool outputs from it.

## Evaluation

See `eval/results/<run>/EVALUATION_REPORT.md` and `summary.json`. Suites:

1. Controls: tool output vs. an independent SQLite implementation and vs. the v1.0 recorded output, on identical archived snapshots (FL DR-4734 cost share, 238 rows; FL DR-4673 repeats, 3,964 rows; FL DR-4673 Category C, 179 rows).
2. Errors: 15 invalid-argument, injection, and not-found cases, plus 4 simulated upstream failures (503, 429, invalid JSON, missing record list).
3. Contract: exact tool set, read-only annotations, every input field described, and an output schema on every tool.
4. Stability: 10 identical calls per tool return identical results (timestamps excluded). Latency is recorded.
5. Live (opt-in): LA DR-4611 Category F, NC DR-4827 repeats, evidence brief PW 1725, and review queue LA DR-4611, each compared with a direct OpenFEMA query written independently of the server code.

Limits: the model-in-the-loop measurements (tool selection 15/15, golden sets, baseline 15/15 vs 0/15) were recorded on v1.0 tool names and descriptions. They have not been re-run on v1.1.
