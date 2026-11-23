# Evaluation methodology

The maintained methodology and scenario matrix are in [`evaluation/`](../evaluation/methodology.md).
The harness exercises the server through MCP, compares calculations with independent SQLite
controls, verifies schemas and annotations, tests adversarial failures, and measures repeatability
and latency. Run it with one command:

```sh
uv run python evaluation/evaluate.py
```

Published dated evidence remains under `eval/results/`; new local runs go to
`evaluation/results/latest/`.
