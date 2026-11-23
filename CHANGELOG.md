# Changelog

## 2026-11-23, technical-quality upgrade

- Added bounded retry and exponential delay for retryable OpenFEMA failures.
- Added a bounded short-lived cache that coalesces concurrent identical requests.
- Added content-free structured JSON logging and process-local tool metrics.
- Published operational metrics as the read-only `fema-pa://metrics` resource.
- Added reliability tests for retry recovery, cache coalescing, and metrics privacy.
- Added the one-command `evaluation/evaluate.py` workflow and evaluation matrix.
- Added focused architecture, tool design, governance, evidence-traceability, and audit documents.
- Rewrote the README for engineering and judge review.
- Preserved the pre-change repository at tag `backup/pre-technical-quality-2026-11-23`.
