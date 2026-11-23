# Governance controls

- **Human authority:** outputs are prioritization indicators, never determinations. Every result
  carries the required analyst-review status and limitations.
- **Read-only scope:** tools retrieve public records and calculate indicators. No tool approves,
  denies, changes, deletes, pays, or refers a case.
- **Least data:** tools request explicit OpenFEMA fields and retain no request or response content
  in telemetry.
- **Explainability:** calculations, thresholds, scope, provenance, and limitations are returned in
  structured content.
- **Failure safety:** invalid requests fail before execution; upstream and unexpected failures do
  not expose stack traces, URLs, headers, or credentials.
- **Change evidence:** unit, contract, independent-control, adversarial, and reproducibility checks
  are executable and versioned.
