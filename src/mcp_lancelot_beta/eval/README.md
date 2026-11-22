# Evaluation setup and results

## Reproduce offline

From the root, after `uv sync --extra dev --frozen`:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python eval/run_evaluation.py --output-dir eval/results/my-run
```

The 63 unit and contract tests cover inputs, pure rules, tools, identity, schemas and expected errors. The evaluation makes real MCP calls through an in-memory FastMCP client. It has **33 offline checks**:

The [Word submission package](../docs/FEMA_Oversight_MCP_Submission_Package.docx), Section 11 and Appendices B and D, also supplies the evaluation documentation: methodology, metrics, security, lessons learned and recommendations. [PDF preview](../docs/FEMA_Oversight_MCP_Submission_Package.pdf).

| Suite | Checks | Evidence |
| --- | --- | --- |
| Controls | 3 | Exact tool/SQLite/v1.0 recorded-output agreement on identical snapshots: cost share 238, repeated groups 74, category outliers 3 |
| Errors | 19 | 15 invalid-input/domain cases and 4 simulated upstream cases. Validation errors name fields; domain/upstream errors carry codes and recovery guidance |
| Contract | 5 | Exact six tools, read-only annotations, selection guidance, described inputs, output schemas |
| Stability | 6 | Ten calls per tool, identical results after timestamps are excluded |

The checked-in [November 19 result](results/20261119-local/summary.json) contains the full check results and machine-specific timings. [Pytest XML](results/20261119-local/pytest.xml) records 63 passed tests separately. These denominators must not be added together as one accuracy score.

## Historical live report and fresh live attempt

The [November 18 v1.1 report](results/20261118T094257Z/EVALUATION_REPORT.md) records **37/37**, adding four live checks to the 33 offline checks. It records 115 LA DR-4611 Category F records, 86 NC DR-4827 title groups, a PW 1725 brief re-check, and a LA review queue over 3,648 records. Live latencies of 0.44-0.79 seconds and in-process medians of 6-81 ms belong to that report.

The original repository contained only that human-readable report. Its raw `summary.json` is referenced at a Databricks volume path and was not present for this reconciliation. The historical 37/37 is therefore a dated reported result, not a newly reproduced end-to-end run.

Optional current live run:

```sh
uv run python eval/run_evaluation.py --live --output-dir eval/results/my-live-run
```

The November 19 live retry is stored [separately](results/20261119-live-attempt/): **37/37 passed**, run `20261119T134625Z`, with complete machine-readable results. The first attempt stopped on an upstream timeout. The completed retry measured live calls at 0.26-13.95 seconds and snapshot in-process medians at 7.2-100.8 ms. These are four individual live calls and ten snapshot calls per tool, not an uptime or throughput study. The directory name records that this began as a live verification attempt; its summary establishes the successful outcome.

## Fixtures and controls

[`fixtures/openfema-20261102.zip`](fixtures/openfema-20261102.zip) contains only seven files needed by the harness from recorded run `20261102T152007Z`: three public OpenFEMA snapshots, three recorded control comparisons, and the run summary. It is extracted without changing the JSON content from the historical submission bundle retained in Git history. The fixture manifest records hashes and origin.

Source fingerprint: SHA-256 over sorted `src/**/*.py`, concatenating each POSIX relative path and source bytes with CRLF normalized to LF. It excludes documentation, tests, harness and packaging. A separate release manifest hashes the submitted files. [Claims register](../docs/CLAIMS_REGISTER.md).

## Limits of these results

This evaluates rule implementation, contract behavior and reproducibility. It does not estimate detection precision, recall, operational uptime, reviewer agreement, cost savings or model tool-selection accuracy. Stability excludes timestamps and uses archived inputs. A historical tampering exercise is described in the November 18 report, but is not counted among the 33 current checks. Old v1.0 model/golden-set/baseline numbers do not describe v1.1.

Actual stdio and HTTP startup, discovery of six tools/two resources/one prompt, and a static explanation call were also verified. This is a separate packaging smoke check, not part of the 37:

```sh
uv run python eval/smoke_transports.py --output eval/results/my-transport-smoke.json
```
