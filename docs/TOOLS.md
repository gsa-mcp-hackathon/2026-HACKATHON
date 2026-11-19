# MCP tool contract and examples

All six tools publish Pydantic input and output schemas. Each accepts a single input field named **`params`**. Pass the nested JSON shown below; flat keyword arguments are shorthand in conversation, not the actual MCP wire format. Unknown fields are rejected.

| Tool | Required fields inside params | Result |
| --- | --- | --- |
| `build_review_queue` | `state_code`, `disaster_number` | Queue, reasons, totals, data scope, provenance, caveat |
| `screen_category_cost_outliers` | `damage_category_code` plus state and/or disaster | Indicators, population statistics, pagination, data scope, provenance, caveat |
| `find_repeated_worksheet_groups` | State and/or disaster | Title groups, match type, pagination, data scope, provenance, caveat |
| `screen_cost_share_ratios` | `state_code` | Ratios, band position, pagination, policy context, data scope, provenance, caveat |
| `explain_review_indicator` | `indicator` | Static methodology card; no network call, retrieval timestamp, or data-scope block |
| `prepare_evidence_brief` | `pw_number`, `disaster_number`, `indicator` | Source records, identity, default-rule re-check, method, next steps, provenance and caveat; no top-level data-scope block |

`indicator` is one of `category_outlier`, `repeated_worksheet`, `cost_share_ratio`. Damage category is A-G. Include `applicant_id` in a brief to resolve the full disaster/applicant/PW identity. Without it, multiple applicants produce an ambiguity error.

## Three-step demonstration

Call `build_review_queue`:

```json
{"params":{"state_code":"LA","disaster_number":4611,"limit":5}}
```

Call `screen_category_cost_outliers`:

```json
{"params":{"state_code":"LA","disaster_number":4611,"damage_category_code":"F"}}
```

Call `prepare_evidence_brief`:

```json
{"params":{"pw_number":1725,"disaster_number":4611,"applicant_id":"109-99109-00","indicator":"category_outlier"}}
```

To inspect the method, call `explain_review_indicator` with `{"params":{"indicator":"category_outlier"}}`.

Screens default to 25 returned results and support `offset` and `limit` (1-100). Follow `page.next_offset` until `has_more` is false to count every screen result. The review queue returns up to 100 entries and reports the total matching worksheets, but does not have screen-style pagination.

All tools advertise `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`. Live calls can still change as the public source changes. Resources: `fema-pa://provenance`, `fema-pa://methodology`. Prompt: `disaster_review(state_code, disaster_number)`.

## Read the rule before interpreting the result

- Category: `(projectAmount - mean) / population_stddev >= sigma_threshold`, default 3.0. Only numeric values in the retrieved category form the baseline. These are not matched engineering peers.
- Repeats: lowercase titles, remove punctuation and standalone numbers, group within disaster/applicant/category. The default minimum is two retrieved rows in a group. Duplicate upstream rows are not deduplicated by this grouping function, so compare the distinct PW list before interpreting a group. Same wording and numbered series are labeled separately. Similar titles do not establish duplicated benefits.
- Cost share: federal share obligated divided by total obligated, default amount floor $100,000. Return ratios below 0.70 or above 0.95. Equality at a boundary is inside the band. Authorized 90% or 100% shares may be legitimate and are not verified here.
- Queue: one retrieval, all three rules, merge by disaster/applicant/PW, rank by distinct indicator count then project amount. It is not a calibrated risk score. Indicator totals can overlap and use different units: category/cost-share totals count matching rows, while the repeated-worksheet total counts groups. Do not add these totals or interpret them as distinct projects.
- Brief: re-checks the requested rule with default thresholds. A previous custom screen's thresholds are not carried forward. Review the returned `indicator_check` rather than assuming the original indicator remains true.

See the authoritative [inputs](../src/fema_oversight/schemas/inputs.py), [outputs](../src/fema_oversight/schemas/outputs.py), [rules](../src/fema_oversight/indicators.py) and [methodology](../src/fema_oversight/methodology.py).
