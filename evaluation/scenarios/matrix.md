# Evaluation matrix

| Scenario | Expected result | Evidence |
| --- | --- | --- |
| Category cost outliers | MCP identities equal independent population-standard-deviation control | `controls/category` |
| Repeated worksheet titles | Groups equal independent normalized-title SQL control | `controls/repeated` |
| Cost-share ratios | Identities equal independent ratio-band SQL control | `controls/cost_share` |
| Review queue | Deterministic ranking with reasons and provenance | `contract` and unit tests |
| Missing or invalid identifiers | Structured, actionable MCP error with no stack trace | `errors` |
| Unknown arguments | Pydantic rejects the request before tool execution | `errors` |
| Empty or insufficient populations | `NOT_FOUND` or `INSUFFICIENT_DATA` as applicable | `errors` |
| Malformed or oversized upstream response | Sanitized, typed failure; no partial output | `errors` |
| Repeated identical calls | Identical structured content | `stability` |
| OpenFEMA transient failure | Bounded retry, then success or retryable error | `tests/test_reliability.py` |
| Concurrent duplicate query | One upstream call through the single-flight cache | `tests/test_reliability.py` |
| Operational metrics | Counts and latency exposed without request content | `tests/test_reliability.py` |
