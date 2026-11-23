# FEMA Oversight MCP

FEMA Oversight MCP is a read-only Model Context Protocol server that turns public FEMA Public
Assistance records into traceable review queues, documented screening indicators, and worksheet
evidence briefs. It helps an analyst decide where to look. It does not decide eligibility,
allowability, fraud, payment, enforcement, or case disposition.

- Server name: `FEMA Evidence & Oversight Graph`
- Submission: Dataset Access Server track, version 1.1
- Authors: Phebe Arouni and Tom Jacobson

## Why it exists

OpenFEMA exposes useful project records, but an agent needs more than endpoint wrappers. It needs
actions that answer reviewer questions, explain calculations, preserve source identity, and state
what the evidence cannot establish. This server supplies those actions as strict MCP contracts.

## Core design principles

### 1. Deterministic evidence generation

Review indicators are ordinary Python calculations. They do not depend on an LLM, hidden prompt,
or model judgment. Identical records and thresholds produce identical results.

### 2. Complete evidence traceability

Each data response includes the dataset, publisher, retrieval time, refresh value, executed rule,
filters, record cap, truncation signal, limitations, and stable FEMA identifiers.

### 3. Human decision authority

Every result is a review indicator. Tools never approve, deny, alter, delete, pay, refer, or label
a project. A person decides what, if anything, follows.

## Architecture

```text
Agent or MCP client
        │ strict Pydantic request
        ▼
 FastMCP tool layer ─── structured logs and aggregate metrics
        │
        ├── review actions and orchestration
        ├── pure deterministic indicators
        ├── shared methodology and provenance
        └── fixed-origin OpenFEMA data source
                         │
              retry + timeout + size limit
              short cache + request coalescing
                         ▼
                OpenFEMA PA v2
```

See [Architecture](docs/Architecture.md), [Tool design](docs/ToolDesign.md), and
[Evidence traceability](docs/EvidenceTraceability.md).

## Tool catalog

| Tool | User goal | Main input | Structured output |
| --- | --- | --- | --- |
| `build_review_queue` | Decide where to begin in a disaster | State, disaster, limit | Ranked worksheets with distinct reasons |
| `screen_category_cost_outliers` | Find unusually costly comparable work | Category plus state or disaster | Projects, sigma, baseline, scope, provenance |
| `find_repeated_worksheet_groups` | Find potentially related worksheets | State or disaster | Groups, match type, worksheet identities |
| `screen_cost_share_ratios` | Find shares outside a chosen band | State, optional disaster and thresholds | Ratios, band position, policy caution |
| `prepare_evidence_brief` | Assemble evidence for one worksheet | PW, disaster, indicator, optional applicant | Source record, recheck, method, next steps |
| `explain_review_indicator` | Understand an indicator without a data call | Indicator name | Calculation, thresholds, reading guidance, limits |

Descriptions tell an agent when to use each tool and when not to. Inputs reject unknown fields.
Outputs are Pydantic models published as MCP `outputSchema` and returned as structured content.

## Reliability

- Fixed `https://www.fema.gov/api/open/` origin and fixed dataset path.
- Redirects and environment proxies disabled.
- Thirty-second request timeout and 20 MB response ceiling.
- Bounded three-attempt retry for transient failures.
- Sixty-second, 128-entry cache with concurrent request coalescing; failures are not cached.
- Stable, actionable MCP error codes with masked unexpected details.
- JSON logs containing tool name, request ID, duration, outcome, and safe error category only.
- `fema-pa://metrics` resource for process-local counts and latency without request content.

See [Security](SECURITY.md) and [Governance controls](docs/GovernanceControls.md).

## Evaluation

The evaluation uses the real MCP server through an in-process client and compares its calculations
with independent SQLite controls over a fixed public OpenFEMA snapshot. It also verifies tool
contracts, adversarial failures, deterministic repetition, and latency.

```sh
uv sync --extra dev --frozen
uv run pytest -q
uv run python evaluation/evaluate.py
```

The second command writes `evaluation/results/latest/summary.json` and
`EVALUATION_REPORT.md`; it exits nonzero on any failed check. See the
[methodology](evaluation/methodology.md) and [scenario matrix](evaluation/scenarios/matrix.md).
Published dated release evidence remains under [`eval/results/`](eval/results/).

## Running locally

Requirements: Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/gsa-mcp-hackathon/2026-HACKATHON.git
cd 2026-HACKATHON
uv sync --extra dev --frozen
uv run python main.py
```

The default transport is stdio. `PORT` or `DATABRICKS_APP_PORT` selects streamable HTTP at `/mcp`.
Offline tests require no FEMA key, model account, or Databricks login. Live tools require outbound
access to OpenFEMA.

## MCP integration

Example stdio client configuration:

```json
{
  "mcpServers": {
    "fema-oversight": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/2026-HACKATHON"
    }
  }
}
```

The server also publishes:

- `fema-pa://provenance`, dataset identity and field definitions.
- `fema-pa://methodology`, executable-rule explanations.
- `fema-pa://metrics`, content-free process metrics.
- `disaster_review`, an evidence-first review prompt.

## Example agent interactions

> Build a prioritized review queue for Florida disaster 4673, then prepare an evidence brief for
> the highest-ranked worksheet.

The agent should call `build_review_queue`, preserve the returned identifiers, then call
`prepare_evidence_brief` with the first indicator. It should report the scope and provenance and
end with the returned analyst-review status.

> Which Category C projects in DR-4673 are at least three standard deviations above their peers?

The agent should call `screen_category_cost_outliers` with `damage_category_code: "C"` and
`disaster_number: 4673`, then report the baseline and truncation signal with the results.

> Why was this worksheet flagged for cost share?

The agent should call `explain_review_indicator` for `cost_share_ratio`, not infer policy approval
from the numerical screen.

## Repository map

```text
src/fema_oversight/       canonical Python MCP server
tests/                    unit, contract, failure, and reliability tests
evaluation/               one-command evaluation entry point and methodology
eval/                     published harness, fixtures, and dated evidence
docs/                     architecture, governance, traceability, and release records
src/lancelot_client/      separate Databricks client project
src/mcp_lancelot_beta/    separate Lancelot beta server project
```

The technical-quality changes are listed in [CHANGELOG](CHANGELOG.md), with the audit in
[TECHNICAL_QUALITY_AUDIT](docs/TECHNICAL_QUALITY_AUDIT.md). The pre-refactor state is preserved at
tag `backup/pre-technical-quality-2026-11-23`.

## Data and limitations

Source: [OpenFEMA Public Assistance Funded Projects Details v2](https://www.fema.gov/openfema-data-page/public-assistance-funded-projects-details-v2).
Estimated project amounts, obligations, and payments are different measures. Grants Manager data
is not FEMA's official financial reporting. Category outliers can be legitimate large projects;
repeated titles can be valid sites or phases; cost-share screens do not check declaration-specific
authorizations. No production authorization or analyst-effectiveness claim is made.

Adapted from the [GSA MCP hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template).
Licensed under [MIT](LICENSE), including the original TTS notice.
