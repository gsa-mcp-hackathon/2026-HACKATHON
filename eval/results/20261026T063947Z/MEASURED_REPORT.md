# Measured Databricks Evaluation

Run: 20261026T063947Z
Source SHA-256: 0c3f6f2b321266d641eadb115154e9544cda54b25cb42ef71dfe3f6323700e53

## Functional checks

| Check | Pass |
|---|---|
| pytest | True |
| ruff | True |
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
| pytest_cases | 49 |
| pytest_passed | 49 |
| get_cost_share_anomalies_median_seconds | 0.3629366839999193 |
| find_repeated_worksheets_median_seconds | 0.40286464300004354 |
| detect_category_outliers_median_seconds | 0.36611285599997245 |
| tool_selection_correct | 15 |
| tool_selection_cases | 15 |
| completed_agent_workflows | 3 |
| agent_workflow_cases | 3 |

## Scope and limits

Functional tests use the actual registered FastMCP tools in process inside Databricks. Detection controls use SQLite against identical archived OpenFEMA snapshots. Live latency includes retrieval and calculation, but excludes remote MCP transport and LLM time. Tool selection measures first tool name on 15 explicit held-out questions, not general answer accuracy. Agent traces are genuine model and tool responses. No hallucination-rate or semantic correctness claim is made. Retrieved data is capped and may be incomplete. The API-backed implementation does not execute these calculations through Unity Catalog functions. Cost-share thresholds do not verify declaration authorization. Category peers are limited to the selected category and filters. Human review remains required.