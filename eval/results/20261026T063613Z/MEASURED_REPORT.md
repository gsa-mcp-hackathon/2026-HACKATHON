# Measured Databricks Evaluation

Run: 20261026T063613Z
Source SHA-256: a7ac29d8e0f268b336b4b5aad9cf77ad3f89bdebe35959544b94c7d78b8f2bf3

## Functional checks

| Check | Pass |
|---|---|
| pytest | False |
| cost_share_sqlite_control | True |
| repeated_sqlite_control | True |
| category_sqlite_control | True |
| get_cost_share_anomalies_live | True |
| find_repeated_worksheets_live | True |
| detect_category_outliers_live | True |
| explanation_schema | True |
| evidence_identity | True |

## Measured metrics

| Metric | Value |
|---|---|
| get_cost_share_anomalies_median_seconds | 0.3666552010000146 |
| find_repeated_worksheets_median_seconds | 0.4389288230000261 |
| detect_category_outliers_median_seconds | 0.3661850059999665 |
| tool_selection_correct | 15 |
| tool_selection_cases | 15 |
| completed_agent_workflows | 3 |
| agent_workflow_cases | 3 |

## Scope and limits

Functional tests use the actual registered FastMCP tools in process inside Databricks. Detection controls use SQLite against identical archived OpenFEMA snapshots. Live latency includes retrieval and calculation, but excludes remote MCP transport and LLM time. Tool selection measures first tool name on 15 explicit held-out questions, not general answer accuracy. Agent traces are genuine model and tool responses. No hallucination-rate or semantic correctness claim is made. Retrieved data is capped and may be incomplete. The API-backed implementation does not execute these calculations through Unity Catalog functions. Cost-share thresholds do not verify declaration authorization. Category peers are limited to the selected category and filters. Human review remains required.