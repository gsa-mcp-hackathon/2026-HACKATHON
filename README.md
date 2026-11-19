# FEMA Oversight MCP

**Start here, judges:** [submission package](SUBMISSION.md), [judges deck](presentation/FEMA_Oversight_MCP_Judges_Deck.pptx), [editable Word package](docs/FEMA_Oversight_MCP_Submission_Package.docx).

Public-data review preparation for FEMA Public Assistance. Six read-only MCP tools turn OpenFEMA funded-project records into a ranked review queue, documented screening results, and a worksheet evidence brief. Code computes the indicators. A human decides whether further review is warranted.

MCP discovery displays the server name `FEMA Evidence & Oversight Graph`; the submission title is FEMA Oversight MCP. [Preview the slides as PDF](presentation/FEMA_Oversight_MCP_Judges_Deck.pdf) or [read the package as PDF](docs/FEMA_Oversight_MCP_Submission_Package.pdf).

Phebe Arouni and Tom Jacobson. Dataset Access Server track. Sandbox prototype, server **1.1.0**, reconciled November 19, 2026.

## Follow the submission in five minutes

| Judge task | Direct path |
| --- | --- |
| Understand the problem and examples | [Submission package](SUBMISSION.md) and deck slides 1-8 |
| See how the GSA template was used | [Template adaptation with pinned upstream links](docs/GSA_TEMPLATE_ALIGNMENT.md) |
| Inspect the six tools and exact MCP arguments | [Tool contract and examples](docs/TOOLS.md) |
| Reproduce the results without a Databricks account | [Quickstart](QUICKSTART.md), then [evaluation guide](eval/README.md) |
| Trace a number to its source and date | [Claims register](docs/CLAIMS_REGISTER.md) |
| Check security and remaining limits | [Security](SECURITY.md) and [technical design](docs/TECHNICAL_DESIGN.md) |

## Verified results and scope

- November 19 local verification: **63/63 unit and contract tests**, **33/33 offline MCP evaluation checks**, lint and format checks pass. The checked-in [machine-readable evidence](eval/results/20261119-local/) identifies the source fingerprint and run time.
- November 18 historical v1.1 report: **37/37 checks**, comprising the same 33 offline checks plus four live checks. Its [report](eval/results/20261118T094257Z/EVALUATION_REPORT.md) is retained with its original date. The referenced Databricks-volume raw summary was not included in the original repository.
- November 19 full verification: **37/37 checks passed**, including all four live checks, in run `20261119T134625Z`. An earlier attempt timed out; the retry succeeded. See the [full machine-readable result](eval/results/20261119-live-attempt/summary.json) and [verification status](eval/results/20261119-local/VERIFICATION.md).

These checks evaluate calculations, contracts, errors and repeatability. They do not measure fraud detection, analyst agreement, model tool selection, time saved or operational adoption.

## Run

```sh
uv sync --extra dev --frozen
uv run python main.py
```

Default transport is stdio. Setting `PORT` or `DATABRICKS_APP_PORT` selects streamable HTTP at `/mcp`. No API key, model account or Databricks login is needed for the local server and offline checks. Live tools need internet access to OpenFEMA.

## One submitted implementation

The canonical server is [`src/fema_oversight/server.py`](src/fema_oversight/server.py). Earlier source trees, backup bundles, old decks, duplicate packages and obsolete deployment instructions were removed from the current tree. [Cleanup record](docs/REPOSITORY_CLEANUP.md). Git history retains the earlier files.

The older Databricks analyst app is a separate v1.0 demonstration. This repository does not claim that app runs the submitted v1.1 tools. Judges can evaluate v1.1 locally without it. There is no model-driven web UI or automatic human-approval workflow in v1.1.

## Source and cautions

[OpenFEMA Public Assistance Funded Projects Details v2](https://www.fema.gov/openfema-data-page/public-assistance-funded-projects-details-v2). Estimated project amounts, obligations and payments are different measures. These public Grants Manager records are not official financial reporting. Category outliers use retrieved-category statistics, repeated titles can describe legitimate work, and cost-share authorizations are not verified. All outputs are review indicators requiring human judgment.

Adapted from the [GSA MCP hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template). [MIT license](LICENSE), including the original TTS notice. No agency endorsement or production authorization is claimed.
