# Verification status on November 19 2026

Submitted server: 1.1.0. Canonical source: root `src/fema_oversight/`.
Source SHA-256: `6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98`.

| Check | Outcome | Evidence |
| --- | --- | --- |
| Unit and contract tests | 63 passed, 0 failures | pytest.xml |
| Offline MCP evaluation | 33/33, run 20261119T134540Z | summary.json |
| Complete MCP evaluation with live OpenFEMA | 37/37, run 20261119T134625Z | ../20261119-live-attempt/summary.json |
| Ruff lint and formatting | Pass | checks.json |
| First live attempt | Incomplete, OpenFEMA timeout | disclosed here; no pass claimed for that attempt |

Windows, CPython 3.12.15 x64, FastMCP 2.14.7. Dependencies are pinned in root uv.lock. Two upstream Authlib deprecation warnings occurred during pytest; they did not fail tests.

The live retry returned 115 LA DR-4611 Category F records, 86 NC DR-4827 repeated-title groups over 3,107 records, a successful PW 1725 rule re-check and a LA DR-4611 queue over 3,648 records. Current live latencies: 0.44 s category, 0.26 s repeats, 1.95 s brief, 13.95 s queue. Each is one observed call, not a service-level guarantee.

No v1.1 hosted deployment, production authorization, analyst study or model-selection evaluation was performed. The older Databricks app is a separate v1.0 demo. The actual MCP calls in demo.json do not involve an LLM.
