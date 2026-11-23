# Evaluation methodology

The evaluation calls the real FastMCP server through an in-process MCP client. It does not
call Python implementation functions directly. Results are compared with independent SQLite
calculations over a fixed OpenFEMA snapshot, which separates contract validation from rule
validation.

## What is tested

- Tool discovery, exact names, descriptions, annotations, input schemas, and output schemas.
- Category-outlier, repeated-title, and cost-share calculations against independent controls.
- Review queue ranking, evidence traceability, provenance, and deterministic repetition.
- Invalid identifiers, unknown fields, empty populations, ambiguous worksheets, malformed
  upstream responses, response-size limits, timeouts, and sanitized errors.
- Latency for repeated in-process calls. Optional live checks compare the server with a direct
  OpenFEMA query but are not required for the reproducible offline result.

## Dataset and expected behavior

`eval/fixtures/openfema-20261102.zip` is the immutable recorded input. Its checksum and contents
are documented by `eval/fixtures/MANIFEST.json`. Expected identities are calculated independently
with SQLite during each run rather than copied from the server output.

## Reproduce

```sh
uv sync --extra dev --frozen
uv run python evaluation/evaluate.py
```

The command writes machine-readable `summary.json` and a readable `EVALUATION_REPORT.md` under
`evaluation/results/latest/`. It exits nonzero if any check fails.

## Interpretation limits

Passing checks establish contract behavior, deterministic calculations, failure handling, and
traceability for the tested inputs. They do not establish fraud detection, legal sufficiency,
analyst agreement, production authorization, or operational impact.
