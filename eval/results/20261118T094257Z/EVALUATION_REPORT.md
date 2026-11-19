# Evaluation report, run 20261118T094257Z

* Server version: 1.1.0
* Source fingerprint (SHA-256 of src/**/*.py): `6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98`
* Snapshots: recorded run 20261102T152007Z
* Result: 37 of 37 checks passed
* Machine-readable results: `/Volumes/users/phebe_arouni/hackathon_submissions/20261118_v1_1_eval/20261118T094257Z/summary.json` (sha256 `6ab650fcb8f6bf833e956084b5b6bdaa500368e567abafd0008d6078184a2b6a`)

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
| live | live: LA DR-4611 Cat F outliers vs direct query | PASS | {"records": 115, "control_records": 115, "pw_numbers": [1725, 1679, 5757], "sigma": [7.73, 4.75, 3.29]} |
| live | live: NC DR-4827 repeated groups vs direct query | PASS | {"groups": 86, "control_groups": 86, "same_wording": 2, "records": 3107} |
| live | live: evidence brief PW 1725 re-checks indicator | PASS | {"indicator_check": {"indicator_met": true, "measured_value": "sigma 7.73 ($149,603,170.72)", "threshold": "sigma >= 3.0", "baseline": "115 category F projects, |
| live | live: review queue LA DR-4611 builds | PASS | {"top": [[966, 3], [2106, 3], [732, 3], [2105, 3], [1900, 3]], "indicator_totals": {"category_outlier": 55, "repeated_worksheet": 134, "cost_share_ratio": 1510} |

Latency (in-process MCP calls on snapshots, ms; live calls in seconds):

```
{
  "screen_category_cost_outliers": {"p50_ms": 43.5, "max_ms": 58.0, "calls": 10},
  "find_repeated_worksheet_groups": {"p50_ms": 61.3, "max_ms": 143.5, "calls": 10},
  "screen_cost_share_ratios": {"p50_ms": 42.3, "max_ms": 48.7, "calls": 10},
  "build_review_queue": {"p50_ms": 80.7, "max_ms": 111.5, "calls": 10},
  "prepare_evidence_brief": {"p50_ms": 52.7, "max_ms": 67.9, "calls": 10},
  "explain_review_indicator": {"p50_ms": 6.0, "max_ms": 6.6, "calls": 10},
  "live_seconds": {
    "screen_category_cost_outliers LA-4611-F": 0.55,
    "find_repeated_worksheet_groups NC-4827": 0.44,
    "prepare_evidence_brief PW1725": 0.79,
    "build_review_queue LA-4611": 0.45
  }
}
```

Also run in this session (not part of the 37): 63/63 pytest, ruff check and ruff format clean, and a tampering check (one snapshot amount set to $1e9) that the control comparison correctly reported as a mismatch.

Not re-run on v1.1: model tool selection, golden sets, and the no-tools baseline (those numbers belong to v1.0, run 20261102T152007Z).
