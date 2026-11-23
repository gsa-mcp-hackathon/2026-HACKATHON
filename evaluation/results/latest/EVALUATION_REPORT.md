# Evaluation report, run 20261123T061137Z

* Server version: 1.1.0
* Source fingerprint (SHA-256 of src/**/*.py): `b803aec84eb4e94b6b1cbdf91aa2a4e6cda95b1446437818030a9b6556157c0b`
* Snapshots: recorded run 20261102T152007Z
* Result: 33 of 33 checks passed

| Suite | Check | Result | Detail |
| --- | --- | --- | --- |
| controls | control_cost_share | PASS | {"snapshot_rows": 238, "tool_count": 238, "sqlite_control_count": 238, "v1_0_recorded_count": 238, "matches_sqlite": true, "matches_v1_0": true} |
| controls | control_repeated | PASS | {"snapshot_rows": 3964, "tool_count": 74, "sqlite_control_count": 74, "v1_0_recorded_count": 74, "matches_sqlite": true, "matches_v1_0": true} |
| controls | control_category | PASS | {"snapshot_rows": 179, "tool_count": 3, "sqlite_control_count": 3, "v1_0_recorded_count": 3, "matches_sqlite": true, "matches_v1_0": true} |
| errors | error: unknown damage category | PASS | {"tool": "screen_category_cost_outliers"} |
| errors | error: missing scope | PASS | {"tool": "screen_category_cost_outliers"} |
| errors | error: sigma out of range | PASS | {"tool": "screen_category_cost_outliers"} |
| errors | error: three-letter state | PASS | {"tool": "screen_cost_share_ratios"} |
| errors | error: OData injection in state | PASS | {"tool": "screen_cost_share_ratios"} |
| errors | error: inverted band | PASS | {"tool": "screen_cost_share_ratios"} |
| errors | error: ratio above 1 | PASS | {"tool": "screen_cost_share_ratios"} |
| errors | error: repeat count 1 | PASS | {"tool": "find_repeated_worksheet_groups"} |
| errors | error: misspelled argument | PASS | {"tool": "find_repeated_worksheet_groups"} |
| errors | error: negative offset | PASS | {"tool": "find_repeated_worksheet_groups"} |
| errors | error: queue without disaster | PASS | {"tool": "build_review_queue"} |
| errors | error: unknown indicator | PASS | {"tool": "explain_review_indicator"} |
| errors | error: OData injection in applicant | PASS | {"tool": "prepare_evidence_brief"} |
| errors | error: worksheet not found | PASS | {"tool": "prepare_evidence_brief"} |
| errors | error: category with no data | PASS | {"tool": "screen_category_cost_outliers"} |
| errors | upstream: HTTP 503 | PASS | [UPSTREAM_UNAVAILABLE] OpenFEMA returned HTTP 503. Hint: Retry in a few seconds. Retryable: yes |
| errors | upstream: HTTP 429 | PASS | [UPSTREAM_UNAVAILABLE] OpenFEMA returned HTTP 429. Hint: Retry in a few seconds. Retryable: yes |
| errors | upstream: invalid JSON | PASS | [UPSTREAM_INVALID_RESPONSE] OpenFEMA returned invalid JSON. Hint: Retry later. Retryable: yes |
| errors | upstream: missing record list | PASS | [UPSTREAM_INVALID_RESPONSE] OpenFEMA returned a response without a valid record list. Hint: Retry later; the dataset may |
| contract | contract: exact tool set | PASS | {"tools": ["build_review_queue", "explain_review_indicator", "find_repeated_worksheet_groups", "prepare_evidence_brief", "screen_category_cost_outliers", "scree |
| contract | contract: all tools read-only | PASS |  |
| contract | contract: USE WHEN / DO NOT USE in every description | PASS |  |
| contract | contract: every input field described | PASS | {"undocumented": []} |
| contract | contract: every tool has an output schema | PASS |  |
| stability | stable: screen_category_cost_outliers | PASS | {"repeats": 10} |
| stability | stable: find_repeated_worksheet_groups | PASS | {"repeats": 10} |
| stability | stable: screen_cost_share_ratios | PASS | {"repeats": 10} |
| stability | stable: build_review_queue | PASS | {"repeats": 10} |
| stability | stable: prepare_evidence_brief | PASS | {"repeats": 10} |
| stability | stable: explain_review_indicator | PASS | {"repeats": 10} |

Latency (in-process MCP calls on snapshots, ms; live calls in seconds):

```
{
  "screen_category_cost_outliers": {
    "p50_ms": 50.3,
    "max_ms": 53.1,
    "calls": 10
  },
  "find_repeated_worksheet_groups": {
    "p50_ms": 70.6,
    "max_ms": 106.4,
    "calls": 10
  },
  "screen_cost_share_ratios": {
    "p50_ms": 44.6,
    "max_ms": 47.7,
    "calls": 10
  },
  "build_review_queue": {
    "p50_ms": 97.0,
    "max_ms": 130.5,
    "calls": 10
  },
  "prepare_evidence_brief": {
    "p50_ms": 63.1,
    "max_ms": 70.7,
    "calls": 10
  },
  "explain_review_indicator": {
    "p50_ms": 7.1,
    "max_ms": 8.6,
    "calls": 10
  }
}
```
